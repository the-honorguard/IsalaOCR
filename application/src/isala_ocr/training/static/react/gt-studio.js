/* Generated runtime for frontend/src/gt-studio.ts. */
(function(){
  const h=React.createElement;
  function GTStudio(props){
    const image=props.image;
    return h('section',{className:'gt-studio'},
      h('header',null,h('h2',null,'GT Studio / Review Studio'),h('span',null,image?image.status:'no image')),
      h('div',{className:'gt-studio-layout'},
        h('div',{className:'gt-viewer'},image&&image.image_url?h('img',{src:image.image_url,alt:'Ground truth review'}):h('div',null,'Image viewer')),
        h('aside',{className:'gt-controls'},
          h('button',{onClick:props.onPrevious},'Previous'),
          h('button',{onClick:props.onNext},'Next'),
          h('button',{onClick:props.onApprove},'Approve GT'),
          h('button',{onClick:props.onToggleTraining},'Toggle training')
        )
      )
    );
  }
  const bootstrap=window.__ISALA_GT_STUDIO__;
  const root=document.getElementById('gt-studio-root');
  if(root&&bootstrap){ReactDOM.render(h(GTStudio,{image:bootstrap.image,onPrevious:bootstrap.onPrevious,onNext:bootstrap.onNext,onApprove:bootstrap.onApprove,onToggleTraining:bootstrap.onToggleTraining}),root);}
})();
