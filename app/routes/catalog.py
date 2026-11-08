from flask import Blueprint, render_template, request, abort
from sqlalchemy import text
from app.database import get_db
bp=Blueprint('catalog',__name__)
@bp.get('/')
def index():
    q=request.args.get('q','').strip(); media=request.args.get('media','').strip(); year=request.args.get('year','').strip(); artist=request.args.get('artist','').strip()
    sql="""SELECT p.*, mt.name media_name, pp.retail_price, COALESCE(st.stock,0) stock,
    (SELECT group_concat(DISTINCT e.name) FROM product_performances x JOIN performances f ON f.performance_id=x.performance_id LEFT JOIN ensembles e ON e.ensemble_id=f.ensemble_id WHERE x.product_id=p.product_id) artist_name
    FROM products p JOIN media_types mt ON mt.media_type_id=p.media_type_id
    LEFT JOIN product_prices pp ON pp.product_id=p.product_id AND pp.valid_to IS NULL
    LEFT JOIN v_product_stock st ON st.product_id=p.product_id WHERE p.is_active=1"""
    params={}
    if q: sql+=" AND (p.title LIKE :q OR p.catalog_number LIKE :q OR p.description LIKE :q)"; params['q']=f'%{q}%'
    if media: sql+=" AND p.media_type_id=:media"; params['media']=media
    if year: sql+=" AND strftime('%Y',p.release_date)=:year"; params['year']=year
    if artist: sql+=" AND EXISTS (SELECT 1 FROM product_performances x JOIN performances f ON f.performance_id=x.performance_id LEFT JOIN ensembles e ON e.ensemble_id=f.ensemble_id WHERE x.product_id=p.product_id AND e.name LIKE :artist)"; params['artist']=f'%{artist}%'
    sql+=' ORDER BY p.product_id DESC'
    products=get_db().execute(text(sql),params).mappings().all()
    media_types=get_db().execute(text('SELECT * FROM media_types ORDER BY name')).mappings().all()
    return render_template('catalog/index.html',products=products,media_types=media_types,filters={'q':q,'media':media,'year':year,'artist':artist})
@bp.get('/<int:product_id>')
def detail(product_id):
    db=get_db(); p=db.execute(text("SELECT p.*, mt.name media_name, pp.retail_price, COALESCE(st.stock,0) stock FROM products p JOIN media_types mt ON mt.media_type_id=p.media_type_id LEFT JOIN product_prices pp ON pp.product_id=p.product_id AND pp.valid_to IS NULL LEFT JOIN v_product_stock st ON st.product_id=p.product_id WHERE p.product_id=:id AND p.is_active=1"),{'id':product_id}).mappings().first()
    if not p: abort(404)
    tracks=db.execute(text("SELECT x.*, c.title composition_title, e.name ensemble_name FROM product_performances x JOIN performances f ON f.performance_id=x.performance_id JOIN compositions c ON c.composition_id=f.composition_id LEFT JOIN ensembles e ON e.ensemble_id=f.ensemble_id WHERE x.product_id=:id ORDER BY x.disc_number,x.track_number"),{'id':product_id}).mappings().all()
    return render_template('catalog/detail.html',product=p,tracks=tracks)
